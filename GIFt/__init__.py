from collections.abc import Iterator
import torch.nn as nn
from .stragegies import FineTuningStrategy
from .utils import freeze_module,trainable_parameters,class_name
from .meta_types import FinetuableModule

class ModuleIterator(Iterator):
    """
    An iterator that iterates over the layers of a given PyTorch module.
    The iterator returns the layer name, global_name, layer class name, layer object, and a boolean indicating if the layer has child layers.

    Args:
        module (nn.Module): The PyTorch module to iterate over.

    Attributes:
        module (nn.Module): The PyTorch module being iterated over.
        iterations (list): A list of tuples containing the names and layers of the module.
        _index (int): The current index of the iterator.

    Methods:
        __len__(): Returns the number of layers in the module.
        __next__(): Returns the next layer in the iteration.

    """

    def __init__(self, module: nn.Module,parent_name:str) -> None:
        self.module = module
        self.iterations = list(self.module._modules.items())
        self._index = 0
        self.parent_name=parent_name
    
    def __len__(self):
        return len(self.iterations)
    
    def __next__(self):
        if self._index < len(self):
            layer_name, layer = self.iterations[self._index]
            layer_class_name = class_name(layer)
            has_child = True if layer._modules else False
            global_name=self.parent_name+'.'+layer_name if self.parent_name !="" else layer_name
            self._index += 1
            return layer_name, global_name, layer_class_name, layer, has_child
        else:
            raise StopIteration

def modify_modules(module:nn.Module,fine_tuning_strategy:FineTuningStrategy,parent_name:str=""):
    # Replace layers with finetuable layers
    for name, global_name, class_name, current_module, has_child in ModuleIterator(module,parent_name):
        find=False
        if isinstance(current_module,FinetuableModule):
            raise ValueError(f"Layer {global_name} is already finetuable")
        find=fine_tuning_strategy(module,name,global_name,class_name,current_module)
        if not find and has_child:
            modify_modules(current_module,fine_tuning_strategy,global_name)
        else:
            freeze_module(current_module)

def fine_tuning_sd_hook(module, state_dict, *args, **kwargs):
    '''
    Clean the state_dict of the module, removing all the parameters that are not trainable.
    It is better to remove all the parameters that are not trainable from the state_dict rather than create a new state_dict
    rather than create a new state_dict with trainable parameters only. This is because sometimes the state_dict also contains 
    untrainable buffers, which should be kept in the state_dict.
    '''
    new_state_dict = {}
    not_requires_grad_paras=[name for name,param in module.named_parameters() if not param.requires_grad]
    for key, value in state_dict.items():
        if key not in not_requires_grad_paras:
            new_state_dict[key] = value
    return new_state_dict

def fine_tuning_loadsd_posthook(module, incompatible_keys):
    '''
    Enable load_state_dict to load the finetuned model.
    The default load_state_dict will raise an error since it also tries to load the unfinetuned parameters.
    If you don't want to load this hook, you can also set `strick=False` in `load_state_dict` function.
    '''
    finetuned_sd_keys=module.state_dict().keys()
    key_copys=incompatible_keys.missing_keys.copy()
    for key in key_copys:
        if key not in finetuned_sd_keys:
            incompatible_keys.missing_keys.remove(key)

def enable_fine_tuning(module:nn.Module,
                      fine_tuning_strategy:FineTuningStrategy,
                      replace_parameter_function:bool=True):
    """
    Enable fine-tuning for a given module.

    Args:
        module (nn.Module): The module to enable fine-tuning for.
        fine_tuning_strategy (FineTuningStrategy): The strategy to use for fine-tuning.
        replace_parameter_function (bool): Whether to replace the `parameters` function of the module.
            If True, the `parameters` function will only return trainable parameters. This helps you 
            avoiding you modifying your optimizer initialization code. If you set it as False, you 
            can use the `trainable_parameters` function from `GIFt.utils` to get trainable parameters of 
            your network for an optimizer.

    Returns:
        None
    """
    # replace modules
    modify_modules(module,fine_tuning_strategy)
    # add hook to the module to remove untrainable parameters from the state_dict
    module._register_state_dict_hook(fine_tuning_sd_hook)
    # add hook to the module to enable load_state_dict to load the finetuned model
    module.register_load_state_dict_post_hook(fine_tuning_loadsd_posthook)
    # add trainable_parameters function to the module
    if replace_parameter_function:
        setattr(module,"parameters",lambda recurse=True: trainable_parameters(module,recurse))
    
